"""2027 Grand Prize target qualification for ScrollQ.

This module combines ScrollQ's existing scan-quality signal with current,
explicitly versioned public bootstrap metadata. It intentionally does not
invent a single weighted "best scroll" score. Candidates are compared using
a Pareto frontier over two directly inspectable axes:

1. ScrollQ scan-quality score for the exact prize-eligible volume.
2. Existing public segment count for that scroll.

Released surface and lasagna predictions are treated as bootstrap requirements,
not weighted advantages when all candidates share them.

The result is campaign triage, not a readability or ink-presence prediction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_MANIFEST = {
    "as_of": "2026-09-30",
    "prize_url": "https://scrollprize.org/prizes",
    "targets": [
        {
            "scroll": "PHerc0125",
            "volume_id": "20250821151825",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0125",
        },
        {
            "scroll": "PHerc0191",
            "volume_id": "20250821151635",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0191",
        },
        {
            "scroll": "PHerc0211",
            "volume_id": "20250821151803",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0211",
        },
        {
            "scroll": "PHerc0257",
            "volume_id": "20250821151750",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0257",
        },
        {
            "scroll": "PHerc0268",
            "volume_id": "20251110183117",
            "voxel_size_um": 8.64,
            "energy_kev": 116,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0268",
        },
        {
            "scroll": "PHerc0358",
            "volume_id": "20250821151737",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0358",
        },
        {
            "scroll": "PHerc0800",
            "volume_id": "20250521135224",
            "voxel_size_um": 8.64,
            "energy_kev": 116,
            "segments": 6,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0800",
        },
        {
            "scroll": "PHerc0813",
            "volume_id": "20250821151723",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0813",
        },
        {
            "scroll": "PHerc0826",
            "volume_id": "20250821151701",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc0826",
        },
        {
            "scroll": "PHerc1203",
            "volume_id": "20250820131727",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc1203",
            "excluded_same_scroll_higher_res": [
                {
                    "volume_id": "20260319130212",
                    "voxel_size_um": 2.403,
                    "reason": (
                        "The Grand Prize fixes PHerc1203 to volume 20250820131727. "
                        "The prize rules prohibit using data derived from a higher-"
                        "resolution scan of the submitted scroll volume."
                    ),
                }
            ],
        },
        {
            "scroll": "PHerc1218",
            "volume_id": "20250521120456",
            "voxel_size_um": 8.64,
            "energy_kev": 116,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc1218",
        },
        {
            "scroll": "PHerc1447",
            "volume_id": "20250521151220",
            "voxel_size_um": 8.64,
            "energy_kev": 116,
            "segments": 15,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc1447",
        },
        {
            "scroll": "PHerc1545",
            "volume_id": "20250821151648",
            "voxel_size_um": 9.362,
            "energy_kev": 113,
            "segments": 0,
            "surface_prediction": "20260413222639",
            "lasagna_prediction": "20260419180421",
            "source_url": "https://scrollprize.org/data_browser/PHerc1545",
        },
    ],
}


def _match_volume(volumes: list[dict], scroll: str, volume_id: str) -> dict | None:
    """Match only the exact prize volume ID within the requested scroll."""
    needle = f"/{scroll}/volumes/{volume_id}"
    matches = [v for v in volumes if needle in str(v.get("root", ""))]
    if not matches:
        return None
    ok = [v for v in matches if v.get("ok")]
    if ok:
        return max(ok, key=lambda v: float(v.get("score", -1)))
    return matches[0]


def _dominates(a: dict, b: dict) -> bool:
    """Return True when a is no worse on both evidence axes and better on >=1."""
    qa = a.get("quality_score")
    qb = b.get("quality_score")
    if qa is None or qb is None:
        return False
    sa = int(a.get("segments", 0))
    sb = int(b.get("segments", 0))
    return qa >= qb and sa >= sb and (qa > qb or sa > sb)


def qualify(volumes: list[dict], manifest: dict | None = None) -> dict:
    """Build a transparent target-qualification report."""
    manifest = manifest or DEFAULT_MANIFEST
    rows: list[dict] = []

    for target in manifest["targets"]:
        v = _match_volume(volumes, target["scroll"], target["volume_id"])
        row = {
            "scroll": target["scroll"],
            "volume_id": target["volume_id"],
            "voxel_size_um": target["voxel_size_um"],
            "energy_kev": target["energy_kev"],
            "segments": target["segments"],
            "surface_prediction": target["surface_prediction"],
            "lasagna_prediction": target["lasagna_prediction"],
            "source_url": target["source_url"],
            "excluded_same_scroll_higher_res": target.get(
                "excluded_same_scroll_higher_res", []
            ),
            "quality_score": None,
            "quality_root": None,
            "quality_ok": False,
        }
        if v is not None:
            row["quality_ok"] = bool(v.get("ok"))
            row["quality_score"] = v.get("score") if v.get("ok") else None
            row["quality_root"] = v.get("root")
            if not v.get("ok"):
                row["quality_error"] = v.get("error")
        rows.append(row)

    comparable = [
        r
        for r in rows
        if r["quality_score"] is not None
        and r["surface_prediction"]
        and r["lasagna_prediction"]
    ]
    frontier = [
        r["scroll"]
        for r in comparable
        if not any(_dominates(other, r) for other in comparable if other is not r)
    ]
    frontier_set = set(frontier)

    for r in rows:
        if r["quality_score"] is None:
            r["qualification"] = "needs-quality-score"
        elif not (r["surface_prediction"] and r["lasagna_prediction"]):
            r["qualification"] = "missing-geometry-prior"
        elif r["scroll"] in frontier_set:
            r["qualification"] = "pareto-frontier"
        else:
            r["qualification"] = "dominated-on-current-evidence"
            r["dominated_by"] = sorted(
                o["scroll"]
                for o in comparable
                if o is not r and _dominates(o, r)
            )

    return {
        "schema_version": 1,
        "manifest_as_of": manifest["as_of"],
        "prize_url": manifest.get("prize_url"),
        "method": {
            "axes": ["scrollq_quality_score", "existing_segment_count"],
            "rule": (
                "Pareto frontier: maximize scan-quality triage score and existing "
                "segment count. Surface and lasagna predictions are required "
                "bootstrap assets but are not weighted when common to all targets."
            ),
            "warning": (
                "This is campaign triage, not a readability, ink-presence, or "
                "Grand Prize success prediction."
            ),
        },
        "frontier": frontier,
        "targets": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Qualify the fixed 2027 Grand Prize target volumes without inventing "
            "a readability score."
        )
    )
    ap.add_argument("--volumes", required=True, help="volumes.json from scrollq-score")
    ap.add_argument(
        "--targets",
        help="optional JSON manifest overriding the versioned built-in target metadata",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    volumes = json.loads(Path(args.volumes).read_text(encoding="utf-8"))
    manifest = DEFAULT_MANIFEST
    if args.targets:
        manifest = json.loads(Path(args.targets).read_text(encoding="utf-8"))

    result = qualify(volumes, manifest)
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(
        f"qualified {len(result['targets'])} targets; "
        f"Pareto frontier: {', '.join(result['frontier']) or 'none'}"
    )


if __name__ == "__main__":
    main()
