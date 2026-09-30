"""Deterministic geometry-only split for Grand Prize probe candidates.

This module knows nothing about ink scores or visual-quality verdicts. It
turns a frozen candidate pool with 3D bounding boxes into a reproducible
fit/held-out split and verifies that central evaluation cores do not overlap.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


def candidate_z_center(candidate: dict) -> float:
    """Return the midpoint of the candidate bbox along volume z."""
    bbox = candidate.get("bbox")
    if (
        not isinstance(bbox, list)
        or len(bbox) != 2
        or not all(isinstance(p, list) and len(p) == 3 for p in bbox)
    ):
        raise ValueError(f"candidate lacks a valid 3D bbox: {candidate.get('path')}")
    return (float(bbox[0][2]) + float(bbox[1][2])) / 2.0


def split_axial_windows(
    candidates: Iterable[dict],
    *,
    bands: int = 3,
    core_depth: int = 256,
) -> dict:
    """Split paired axial windows without using quality or ink evidence.

    Candidates sharing window_z form one axial window. Windows are sorted by
    bbox-derived z center, divided into equal-count bands, and the window
    nearest each band's mean center is held out. Ties go to the lower center.
    """
    rows = list(candidates)
    if not rows:
        raise ValueError("no candidates")
    if bands < 1:
        raise ValueError("bands must be >= 1")
    if core_depth < 1 or core_depth % 2:
        raise ValueError("core_depth must be a positive even integer")

    grouped: dict[int, list[float]] = {}
    counts: dict[int, int] = {}
    for row in rows:
        if "window_z" not in row:
            raise ValueError("candidate missing window_z")
        window = int(row["window_z"])
        grouped.setdefault(window, []).append(candidate_z_center(row))
        counts[window] = counts.get(window, 0) + 1

    windows = [
        {
            "window_z": window,
            "z_center": sum(values) / len(values),
            "candidate_count": counts[window],
        }
        for window, values in grouped.items()
    ]
    windows.sort(key=lambda r: (r["z_center"], r["window_z"]))

    if len(windows) % bands:
        raise ValueError(
            f"{len(windows)} axial windows cannot be divided equally into {bands} bands"
        )
    band_size = len(windows) // bands
    if band_size < 1:
        raise ValueError("more bands than axial windows")

    held: set[int] = set()
    band_reports = []
    for i in range(bands):
        band = windows[i * band_size : (i + 1) * band_size]
        mean = sum(w["z_center"] for w in band) / len(band)
        chosen = min(
            band,
            key=lambda w: (abs(w["z_center"] - mean), w["z_center"], w["window_z"]),
        )
        held.add(chosen["window_z"])
        band_reports.append(
            {
                "band": i + 1,
                "windows": [dict(w) for w in band],
                "mean_z_center": mean,
                "held_out_window_z": chosen["window_z"],
            }
        )

    half = core_depth // 2
    window_roles = []
    for w in windows:
        center = round(w["z_center"])
        window_roles.append(
            {
                **w,
                "role": "held_out" if w["window_z"] in held else "fit",
                "core_z_half_open": [center - half, center + half],
            }
        )

    minimum_gap = None
    minimum_pair = None
    for i, a in enumerate(window_roles):
        for b in window_roles[i + 1 :]:
            lo = max(a["core_z_half_open"][0], b["core_z_half_open"][0])
            hi = min(a["core_z_half_open"][1], b["core_z_half_open"][1])
            if hi > lo:
                raise ValueError(
                    f"evaluation cores overlap for windows "
                    f"{a['window_z']} and {b['window_z']}"
                )
            gap = max(a["core_z_half_open"][0], b["core_z_half_open"][0]) - min(
                a["core_z_half_open"][1], b["core_z_half_open"][1]
            )
            if minimum_gap is None or gap < minimum_gap:
                minimum_gap = gap
                minimum_pair = [a["window_z"], b["window_z"]]

    role_by_window = {w["window_z"]: w for w in window_roles}
    candidate_roles = []
    for row in rows:
        w = role_by_window[int(row["window_z"])]
        candidate_roles.append(
            {
                "path": row.get("path"),
                "window_z": int(row["window_z"]),
                "wrap": row.get("wrap"),
                "role": w["role"],
                "evaluation_core_z_half_open": w["core_z_half_open"],
            }
        )

    return {
        "method": (
            "Sort bbox-derived axial-window centers; divide into equal-count "
            "bands; hold out the window nearest each band mean, ties to lower z. "
            "All candidates at a held-out window are held out."
        ),
        "uses_quality_or_ink": False,
        "bands": band_reports,
        "core_depth_slices": core_depth,
        "window_roles": window_roles,
        "candidate_roles": candidate_roles,
        "fit_windows": [w["window_z"] for w in window_roles if w["role"] == "fit"],
        "held_out_windows": [
            w["window_z"] for w in window_roles if w["role"] == "held_out"
        ],
        "fit_candidates": sum(
            w["candidate_count"] for w in window_roles if w["role"] == "fit"
        ),
        "held_out_candidates": sum(
            w["candidate_count"] for w in window_roles if w["role"] == "held_out"
        ),
        "core_overlap_check": "pass",
        "minimum_axial_gap_between_any_locked_cores_slices": minimum_gap,
        "minimum_gap_pair_window_z": minimum_pair,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Reproduce a geometry-only fit/held-out split from a locked pool."
    )
    ap.add_argument("--pool", required=True)
    ap.add_argument("--scroll", required=True)
    ap.add_argument("--bands", type=int, default=3)
    ap.add_argument("--core-depth", type=int, default=256)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
    try:
        target = pool["targets"][args.scroll]
        candidates = target["locked_candidates"]
    except KeyError as exc:
        raise SystemExit(f"pool does not contain {args.scroll}: missing {exc}") from exc

    result = {
        "schema_version": 1,
        "scroll": args.scroll,
        "prize_volume_id": target.get("prize_volume_id"),
        "split": split_axial_windows(
            candidates, bands=args.bands, core_depth=args.core_depth
        ),
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{args.scroll}: {result['split']['fit_candidates']} fit / "
        f"{result['split']['held_out_candidates']} held out; "
        f"held windows {result['split']['held_out_windows']}"
    )


if __name__ == "__main__":
    main()
