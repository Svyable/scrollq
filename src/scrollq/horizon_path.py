from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import tifffile


METHOD = "deterministic-first-order-horizon-dp-v1"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_score_map(path: str | Path) -> np.ndarray:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".npy":
        arr = np.load(path, allow_pickle=False)
    elif suffix == ".npz":
        with np.load(path, allow_pickle=False) as z:
            if "score" in z.files:
                arr = z["score"]
            elif len(z.files) == 1:
                arr = z[z.files[0]]
            else:
                raise ValueError("NPZ must contain 'score' or exactly one array")
    elif suffix in {".tif", ".tiff"}:
        arr = tifffile.imread(path)
    else:
        raise ValueError("input must be .npy, .npz, .tif, or .tiff")
    arr = np.asarray(arr)
    if arr.ndim != 2:
        raise ValueError(f"score map must be 2-D, got shape {arr.shape}")
    return arr


def robust_normalize(
    score: np.ndarray,
    lower_percentile: float = 1.0,
    upper_percentile: float = 99.0,
) -> tuple[np.ndarray, dict[str, float]]:
    if not (0.0 <= lower_percentile < upper_percentile <= 100.0):
        raise ValueError("normalization percentiles must satisfy 0 <= low < high <= 100")
    arr = np.asarray(score, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError("score map contains no finite values")
    lo, hi = np.percentile(finite, [lower_percentile, upper_percentile])
    if not math.isfinite(float(lo)) or not math.isfinite(float(hi)) or hi <= lo:
        raise ValueError("normalization percentiles do not span a positive range")
    normalized = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    normalized[~np.isfinite(normalized)] = 0.0
    return normalized, {
        "lower_percentile": float(lower_percentile),
        "upper_percentile": float(upper_percentile),
        "lower_value": float(lo),
        "upper_value": float(hi),
    }


def _canonical_anchors(
    anchors: Iterable[tuple[int, int]],
    *,
    rows: int,
    cols: int,
    max_step: int,
) -> dict[int, int]:
    result: dict[int, int] = {}
    for x_raw, y_raw in anchors:
        x, y = int(x_raw), int(y_raw)
        if not (0 <= x < cols and 0 <= y < rows):
            raise ValueError(
                f"anchor ({x}, {y}) is outside score map bounds "
                f"x=[0,{cols - 1}], y=[0,{rows - 1}]"
            )
        if x in result and result[x] != y:
            raise ValueError(f"conflicting anchors at x={x}: y={result[x]} and y={y}")
        result[x] = y

    ordered = sorted(result.items())
    for (x0, y0), (x1, y1) in zip(ordered, ordered[1:]):
        if abs(y1 - y0) > max_step * (x1 - x0):
            raise ValueError(
                f"anchors ({x0}, {y0}) and ({x1}, {y1}) are unreachable "
                f"with max_step={max_step}"
            )
    return result


def track_horizon(
    score: np.ndarray,
    *,
    max_step: int = 3,
    smoothness: float = 0.15,
    anchors: Iterable[tuple[int, int]] = (),
) -> dict[str, Any]:
    """Track one row-valued path from left to right through a 2-D score map.

    Objective:
        sum_x score[y_x, x] - smoothness * sum_x abs(y_x - y_(x-1))

    Every adjacent step is constrained by max_step. Sparse anchors are hard
    constraints. Ties are resolved deterministically toward the smallest
    previous/current row through NumPy first-argmax behavior.
    """
    arr = np.asarray(score, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("score map must be 2-D")
    rows, cols = arr.shape
    if rows < 1 or cols < 1:
        raise ValueError("score map must be non-empty")
    if not np.isfinite(arr).all():
        raise ValueError("score map must contain only finite values")
    if isinstance(max_step, bool) or int(max_step) != max_step or max_step < 0:
        raise ValueError("max_step must be a non-negative integer")
    max_step = int(max_step)
    if not math.isfinite(smoothness) or smoothness < 0:
        raise ValueError("smoothness must be a finite non-negative number")

    anchor_map = _canonical_anchors(
        anchors, rows=rows, cols=cols, max_step=max_step
    )

    back = np.full((rows, cols), -1, dtype=np.int32)
    prev = arr[:, 0].copy()
    if 0 in anchor_map:
        keep = anchor_map[0]
        prev[:] = -np.inf
        prev[keep] = arr[keep, 0]

    row_ids = np.arange(rows)
    for x in range(1, cols):
        cur = np.full(rows, -np.inf, dtype=np.float64)
        for y in range(rows):
            lo = max(0, y - max_step)
            hi = min(rows, y + max_step + 1)
            candidates = prev[lo:hi] - smoothness * np.abs(row_ids[lo:hi] - y)
            j = int(np.argmax(candidates))
            best = float(candidates[j])
            if math.isfinite(best):
                py = lo + j
                cur[y] = best + arr[y, x]
                back[y, x] = py

        if x in anchor_map:
            keep = anchor_map[x]
            chosen = cur[keep]
            cur[:] = -np.inf
            cur[keep] = chosen
            if not math.isfinite(float(chosen)):
                raise ValueError(
                    f"anchor ({x}, {keep}) is unreachable with max_step={max_step}"
                )

        if not np.isfinite(cur).any():
            raise ValueError(f"no feasible path reaches column x={x}")
        prev = cur

    end_y = int(np.argmax(prev))
    if not math.isfinite(float(prev[end_y])):
        raise ValueError("no feasible horizon path")

    path_y = np.empty(cols, dtype=np.int32)
    path_y[-1] = end_y
    for x in range(cols - 1, 0, -1):
        py = int(back[path_y[x], x])
        if py < 0:
            raise ValueError(f"internal backtracking failure at x={x}")
        path_y[x - 1] = py

    xs = np.arange(cols, dtype=np.int32)
    path_scores = arr[path_y, xs]
    steps = np.abs(np.diff(path_y)).astype(np.int32)
    total_variation = int(steps.sum()) if steps.size else 0
    objective = float(path_scores.sum() - smoothness * total_variation)

    return {
        "path_y": path_y,
        "path_scores": path_scores,
        "objective": objective,
        "data_term": float(path_scores.sum()),
        "smoothness_penalty": float(smoothness * total_variation),
        "total_variation": total_variation,
        "max_observed_step": int(steps.max()) if steps.size else 0,
        "mean_score": float(path_scores.mean()),
        "min_score": float(path_scores.min()),
        "anchors": [
            {"x": int(x), "y": int(y)} for x, y in sorted(anchor_map.items())
        ],
    }


def _parse_anchor(value: str) -> tuple[int, int]:
    try:
        x_raw, y_raw = value.split(":", 1)
        return int(x_raw), int(y_raw)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("anchor must be X:Y using integer indices") from exc


def _load_anchor_file(path: Path) -> list[tuple[int, int]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("anchor JSON must be a list")
    anchors: list[tuple[int, int]] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict) or set(item) != {"x", "y"}:
            raise ValueError(f"anchor JSON row {i} must contain exactly x and y")
        if isinstance(item["x"], bool) or isinstance(item["y"], bool):
            raise ValueError(f"anchor JSON row {i} x/y must be integers")
        try:
            x, y = int(item["x"]), int(item["y"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"anchor JSON row {i} x/y must be integers") from exc
        if x != item["x"] or y != item["y"]:
            raise ValueError(f"anchor JSON row {i} x/y must be integers")
        anchors.append((x, y))
    return anchors


def run(
    input_path: str | Path,
    out_prefix: str | Path,
    *,
    max_step: int = 3,
    smoothness: float = 0.15,
    anchors: Iterable[tuple[int, int]] = (),
    normalize: bool = True,
    lower_percentile: float = 1.0,
    upper_percentile: float = 99.0,
    max_pixels: int = 2_000_000,
) -> dict[str, Any]:
    input_path = Path(input_path)
    out_prefix = Path(out_prefix)
    raw = load_score_map(input_path)
    pixels = int(raw.size)
    if max_pixels <= 0:
        raise ValueError("max_pixels must be positive")
    if pixels > max_pixels:
        raise ValueError(
            f"score map has {pixels:,} pixels, above --max-pixels {max_pixels:,}; "
            "use a smaller slice or explicitly raise the guard"
        )

    if normalize:
        work, normalization = robust_normalize(
            raw,
            lower_percentile=lower_percentile,
            upper_percentile=upper_percentile,
        )
        normalization["enabled"] = True
    else:
        work = np.asarray(raw, dtype=np.float64)
        if not np.isfinite(work).all():
            raise ValueError("non-finite scores require normalization")
        normalization = {"enabled": False}

    result = track_horizon(
        work,
        max_step=max_step,
        smoothness=smoothness,
        anchors=anchors,
    )
    path_y = result.pop("path_y")
    path_scores = result.pop("path_scores")

    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    csv_path = Path(str(out_prefix) + ".horizon.csv")
    json_path = Path(str(out_prefix) + ".horizon.json")

    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["x", "y", "normalized_score", "source_score"])
        for x, y in enumerate(path_y.tolist()):
            writer.writerow(
                [
                    int(x),
                    int(y),
                    format(float(path_scores[x]), ".17g"),
                    format(float(raw[y, x]), ".17g"),
                ]
            )

    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "horizon-path",
        "status": "measured",
        "method": METHOD,
        "scope": (
            "one deterministic 2-D path through a score field; not by itself "
            "evidence of correct papyrus identity, winding identity, or 3-D surface continuity"
        ),
        "input": {
            "path": str(input_path),
            "sha256": _sha256(input_path),
            "shape_yx": [int(v) for v in raw.shape],
            "dtype": str(raw.dtype),
            "pixels": pixels,
        },
        "parameters": {
            "max_step": int(max_step),
            "smoothness": float(smoothness),
        },
        "normalization": normalization,
        "path": {
            **result,
            "points": [
                {"x": int(x), "y": int(y)}
                for x, y in enumerate(path_y.tolist())
            ],
            "csv_path": str(csv_path),
            "csv_sha256": _sha256(csv_path),
        },
    }
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Track one deterministic left-to-right horizon through a 2-D likelihood "
            "map using hard sparse anchors, a maximum step, and a smoothness penalty."
        )
    )
    parser.add_argument("input", help="2-D score map: .npy/.npz/.tif/.tiff")
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--max-step", type=int, default=3)
    parser.add_argument("--smoothness", type=float, default=0.15)
    parser.add_argument(
        "--anchor",
        type=_parse_anchor,
        action="append",
        default=[],
        metavar="X:Y",
        help="hard path anchor; repeat for multiple anchors",
    )
    parser.add_argument(
        "--anchors-json",
        type=Path,
        help='JSON list of {"x": integer, "y": integer} anchor objects',
    )
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--normalize-low", type=float, default=1.0)
    parser.add_argument("--normalize-high", type=float, default=99.0)
    parser.add_argument("--max-pixels", type=int, default=2_000_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    anchors = list(args.anchor)
    try:
        if args.anchors_json is not None:
            anchors.extend(_load_anchor_file(args.anchors_json))
        report = run(
            args.input,
            args.out_prefix,
            max_step=args.max_step,
            smoothness=args.smoothness,
            anchors=anchors,
            normalize=not args.no_normalize,
            lower_percentile=args.normalize_low,
            upper_percentile=args.normalize_high,
            max_pixels=args.max_pixels,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"scroliq-horizon-path: {exc}") from exc
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
