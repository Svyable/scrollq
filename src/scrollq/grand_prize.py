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


def _dominates(a: dict, b: dict, axes: tuple[str, ...]) -> bool:
    """Return True when a is no worse on every axis and better on at least one."""
    av = [a.get(k) for k in axes]
    bv = [b.get(k) for k in axes]
    if any(v is None for v in av) or any(v is None for v in bv):
        return False
    return all(x >= y for x, y in zip(av, bv)) and any(
        x > y for x, y in zip(av, bv)
    )


def _pareto(rows: list[dict], axes: tuple[str, ...]) -> list[str]:
    """Scroll IDs on the weight-free Pareto frontier for complete rows."""
    complete = [r for r in rows if all(r.get(k) is not None for k in axes)]
    return [
        r["scroll"]
        for r in complete
        if not any(
            _dominates(other, r, axes)
            for other in complete
            if other is not r
        )
    ]


def _support_record(
    support_by_scroll: dict[str, dict], target: dict
) -> tuple[dict | None, float | None, str | None]:
    """Validate imported surface-support evidence against the exact prize volume.

    A support number is usable only when its own provenance says it is exact,
    it records the prize-eligible volume ID, and its CT URL contains that same
    volume ID. This makes accidental use of a same-scroll higher-resolution scan
    fail closed.
    """
    record = support_by_scroll.get(target["scroll"])
    if record is None:
        return None, None, "no imported surface-support record"
    if not record.get("usable_for_qualification"):
        return record, None, record.get(
            "exclusion_reason", "surface-support record marked unusable"
        )
    if record.get("volume_match") != "exact":
        return record, None, "surface-support record is not exact-volume evidence"
    if record.get("eligible_volume_id") != target["volume_id"]:
        return record, None, "surface-support record names a different eligible volume"
    ct = str(record.get("survey_ct") or "")
    if target["volume_id"] not in ct:
        return record, None, "surface-support CT URL does not contain prize volume ID"
    support = record.get("sampled_support_frac")
    if not isinstance(support, (int, float)):
        return record, None, "surface-support fraction is missing"
    if not 0.0 <= float(support) <= 1.0:
        return record, None, "surface-support fraction is outside [0, 1]"
    return record, float(support), None


def qualify(
    volumes: list[dict],
    manifest: dict | None = None,
    surface_support: dict | None = None,
) -> dict:
    """Build a transparent target-qualification report.

    The primary result always uses ScrollQ quality and public segment count.
    Optional imported surface-support evidence is reported as a separate
    sensitivity analysis and never changes ScrollQ's published quality score.
    """
    manifest = manifest or DEFAULT_MANIFEST
    support_by_scroll = {
        r["scroll"]: r for r in (surface_support or {}).get("rows", [])
        if isinstance(r, dict) and r.get("scroll")
    }
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
            "surface_support_frac": None,
        }
        if v is not None:
            row["quality_ok"] = bool(v.get("ok"))
            row["quality_score"] = v.get("score") if v.get("ok") else None
            row["quality_root"] = v.get("root")
            if not v.get("ok"):
                row["quality_error"] = v.get("error")

        if surface_support is not None:
            record, support, reason = _support_record(support_by_scroll, target)
            row["surface_support_frac"] = support
            row["surface_support_usable"] = support is not None
            if record is not None:
                row["surface_support_evidence"] = {
                    "survey_path": record.get("survey_path"),
                    "survey_sha": record.get("survey_sha"),
                    "mode": record.get("mode"),
                    "planes_sampled": record.get("planes_sampled"),
                    "planned_planes": record.get("planned_planes"),
                    "survey_ct": record.get("survey_ct"),
                    "volume_match": record.get("volume_match"),
                }
            if reason:
                row["surface_support_exclusion_reason"] = reason
        rows.append(row)

    baseline_axes = ("quality_score", "segments")
    baseline_comparable = [
        r
        for r in rows
        if r["quality_score"] is not None
        and r["surface_prediction"]
        and r["lasagna_prediction"]
    ]
    frontier = _pareto(baseline_comparable, baseline_axes)
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
                for o in baseline_comparable
                if o is not r and _dominates(o, r, baseline_axes)
            )

    result = {
        "schema_version": 2,
        "manifest_as_of": manifest["as_of"],
        "prize_url": manifest.get("prize_url"),
        "method": {
            "axes": ["scrollq_quality_score", "existing_segment_count"],
            "rule": (
                "Primary Pareto frontier: maximize scan-quality triage score and "
                "existing segment count. Surface and lasagna predictions are "
                "required bootstrap assets but are not weighted when common to "
                "all targets."
            ),
            "warning": (
                "This is campaign triage, not a readability, ink-presence, or "
                "Grand Prize success prediction."
            ),
        },
        "frontier": frontier,
        "targets": rows,
    }

    if surface_support is not None:
        support_axes = ("quality_score", "segments", "surface_support_frac")
        support_comparable = [
            r
            for r in baseline_comparable
            if r["surface_support_frac"] is not None
        ]
        support_frontier = _pareto(support_comparable, support_axes)
        excluded = {}
        comparable_scrolls = {r["scroll"] for r in support_comparable}
        for r in rows:
            if r["scroll"] not in comparable_scrolls:
                excluded[r["scroll"]] = r.get(
                    "surface_support_exclusion_reason",
                    "incomplete evidence for support-augmented comparison",
                )
        result["surface_support_analysis"] = {
            "source": surface_support.get("source"),
            "axes": [
                "scrollq_quality_score",
                "existing_segment_count",
                "external_surface_support_fraction",
            ],
            "rule": (
                "Sensitivity-only Pareto frontier among targets with exact-volume "
                "surface-support evidence. It does not replace the primary frontier "
                "and does not alter ScrollQ scores."
            ),
            "comparable_targets": sorted(comparable_scrolls),
            "excluded_targets": excluded,
            "frontier": support_frontier,
        }

    return result


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
    ap.add_argument(
        "--surface-support",
        help=(
            "optional normalized external surface-support evidence; reported as "
            "a separate sensitivity analysis"
        ),
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    volumes = json.loads(Path(args.volumes).read_text(encoding="utf-8"))
    manifest = DEFAULT_MANIFEST
    if args.targets:
        manifest = json.loads(Path(args.targets).read_text(encoding="utf-8"))
    support = None
    if args.surface_support:
        support = json.loads(Path(args.surface_support).read_text(encoding="utf-8"))

    result = qualify(volumes, manifest, support)
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(
        f"qualified {len(result['targets'])} targets; "
        f"primary Pareto frontier: {', '.join(result['frontier']) or 'none'}"
    )
    if "surface_support_analysis" in result:
        print(
            "surface-support sensitivity frontier: "
            + (", ".join(result["surface_support_analysis"]["frontier"]) or "none")
        )


if __name__ == "__main__":
    main()
