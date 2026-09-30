"""Challenge-aligned diagnostic passports for Vesuvius scroll volumes.

The passport is intentionally multi-axis. It records what ScrolIQ can measure,
what evidence is missing, and which Vesuvius Challenge open problem a missing
measurement belongs to. It does not collapse unknown downstream state into the
existing scan-quality score.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

OPEN_PROBLEMS_URL = "https://scrollprize.org/2026_open_problems"
OPEN_PROBLEMS_AS_OF = "2026-07-10"
SCHEMA_VERSION = "1.0"

OPEN_PROBLEMS: tuple[dict[str, str], ...] = (
    {
        "id": "scan-diagnostics",
        "stage": "scan",
        "challenge": "Distinguish locally usable CT signal from compressed or degraded regions.",
        "scroliq": "partial",
    },
    {
        "id": "surface-topology",
        "stage": "unwrapping",
        "challenge": "Preserve recto-surface topology through dense, curved, compressed, and damaged regions.",
        "scroliq": "planned",
    },
    {
        "id": "mesh-connectivity",
        "stage": "unwrapping",
        "challenge": "Detect holes, mergers, sheet switches, and other tracing failures in explicit meshes.",
        "scroliq": "planned",
    },
    {
        "id": "fiber-connectivity",
        "stage": "unwrapping",
        "challenge": "Trace fewer fibers correctly with reliable long-range connectivity.",
        "scroliq": "planned",
    },
    {
        "id": "spiral-fitting",
        "stage": "unwrapping",
        "challenge": "Evaluate global spiral fits, losses, constraints, and under-constrained regions.",
        "scroliq": "planned",
    },
    {
        "id": "label-quality",
        "stage": "training-data",
        "challenge": "Find labels that drift from the physical surface and prioritize high-value corrections.",
        "scroliq": "partial",
    },
    {
        "id": "ink-reliability",
        "stage": "ink-recovery",
        "challenge": "Separate weak signal, surface-placement, label, model, and cross-scroll generalization failures.",
        "scroliq": "planned",
    },
    {
        "id": "data-scale",
        "stage": "infrastructure",
        "challenge": "Keep large-volume workflows cloud-native, reproducible, coordinate-safe, and inspectable.",
        "scroliq": "partial",
    },
)


def alignment_manifest() -> dict[str, Any]:
    """Return the machine-readable ScrolIQ ↔ Open Problems alignment contract."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "url": OPEN_PROBLEMS_URL,
            "page_last_updated": OPEN_PROBLEMS_AS_OF,
        },
        "principle": (
            "Diagnose the limiting stage with explicit evidence; do not collapse "
            "unknown downstream state into one synthetic readiness score."
        ),
        "open_problems": [dict(item) for item in OPEN_PROBLEMS],
    }


def _scan_stage(volume: dict[str, Any]) -> dict[str, Any]:
    if not volume.get("ok"):
        return {
            "status": "blocked",
            "open_problem": "scan-diagnostics",
            "reason": volume.get("error", "volume could not be scored"),
        }

    sampling = dict(volume.get("sampling") or {})
    metrics = dict(volume.get("metrics") or {})
    components = dict(volume.get("components") or {})
    return {
        "status": "measured",
        "open_problem": "scan-diagnostics",
        "quality_score": volume.get("score"),
        "metrics": {
            key: metrics.get(key)
            for key in (
                "nonzero_frac",
                "grad_energy",
                "dyn_range",
                "sat_frac",
                "dead_slices",
                "chunks_decoded",
            )
            if key in metrics
        },
        "components": components,
        "sampling": sampling,
        "limitation": (
            "Current ScrollQ measurements are sparse whole-volume triage, not a "
            "spatial map of compressed/degraded regions."
        ),
    }


def _data_stage(volume: dict[str, Any]) -> dict[str, Any]:
    sampling = dict(volume.get("sampling") or {})
    if not volume.get("ok"):
        return {
            "status": "blocked",
            "open_problem": "data-scale",
            "reason": volume.get("error", "volume could not be read"),
        }

    complete = sampling.get("complete")
    status = "measured" if complete is not False else "partial"
    return {
        "status": status,
        "open_problem": "data-scale",
        "sampling": sampling,
        "evidence": (
            "Real level-0 chunks are decoded through the volcomp path and read "
            "provenance is retained with the score."
        ),
    }


def _label_stage(coverage: dict[str, Any] | None) -> dict[str, Any]:
    if coverage is None:
        return {
            "status": "unknown",
            "open_problem": "label-quality",
            "reason": "no coverage record supplied",
        }
    return {
        "status": "partial",
        "open_problem": "label-quality",
        "ink_labels": coverage.get("ink_labels", 0),
        "segments": coverage.get("segments", 0),
        "label_next": bool(coverage.get("label_next")),
        "limitation": (
            "Coverage measures where labels exist; it does not yet measure whether "
            "surface or fiber labels are physically well localized."
        ),
    }


def _unknown_stage(open_problem: str, reason: str) -> dict[str, str]:
    return {"status": "unknown", "open_problem": open_problem, "reason": reason}


def build_passport(
    volume: dict[str, Any], coverage: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build one evidence-preserving diagnostic passport from current artifacts."""
    root = str(volume.get("root", ""))
    stages = {
        "data": _data_stage(volume),
        "scan": _scan_stage(volume),
        "surface": _unknown_stage(
            "surface-topology",
            "no surface-prediction or surface-support diagnostic was supplied",
        ),
        "mesh": _unknown_stage(
            "mesh-connectivity", "no tifxyz or mesh diagnostic was supplied"
        ),
        "fibers": _unknown_stage(
            "fiber-connectivity", "no fiber tracing evidence was supplied"
        ),
        "spiral": _unknown_stage(
            "spiral-fitting", "no spiral fit or constraint evaluation was supplied"
        ),
        "labels": _label_stage(coverage),
        "ink": _unknown_stage(
            "ink-reliability",
            "no held-out ink inference, leakage audit, or stability evidence was supplied",
        ),
    }

    actions: list[dict[str, str]] = []
    if stages["data"]["status"] == "blocked":
        actions.append(
            {
                "priority": "blocker",
                "action": "repair or re-resolve volume access before downstream analysis",
                "open_problem": "data-scale",
            }
        )
    elif stages["data"]["status"] == "partial":
        actions.append(
            {
                "priority": "high",
                "action": "resolve incomplete sampling/read provenance before trusting scan triage",
                "open_problem": "data-scale",
            }
        )

    if coverage and coverage.get("label_next"):
        actions.append(
            {
                "priority": "high",
                "action": "treat this volume as a candidate for new labels, then measure label localization quality",
                "open_problem": "label-quality",
            }
        )

    actions.extend(
        [
            {
                "priority": "next-evidence",
                "action": "run spatial surface-support/topology diagnostics on released predictions or tifxyz",
                "open_problem": "surface-topology",
            },
            {
                "priority": "next-evidence",
                "action": "validate mesh connectivity and sheet-switch risk before interpreting flattened renders",
                "open_problem": "mesh-connectivity",
            },
            {
                "priority": "next-evidence",
                "action": "require held-out, non-overlapping validation before treating ink output as evidence",
                "open_problem": "ink-reliability",
            },
        ]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "brand": "ScrolIQ",
        "package": "scrollq",
        "volume_root": root,
        "open_problems_source": OPEN_PROBLEMS_URL,
        "stages": stages,
        "next_actions": actions,
        "interpretation": (
            "The existing quality score describes sampled CT health only. Unknown "
            "surface, mesh, spiral, label-localization, fiber, or ink state remains unknown."
        ),
    }


def _select_volume(volumes: list[dict[str, Any]], needle: str) -> dict[str, Any]:
    exact = [v for v in volumes if str(v.get("root", "")) == needle]
    if len(exact) == 1:
        return exact[0]
    matches = [v for v in volumes if needle in str(v.get("root", ""))]
    if len(matches) != 1:
        raise ValueError(
            f"volume selector {needle!r} matched {len(matches)} rows; use an exact root"
        )
    return matches[0]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build a Challenge-aligned ScrolIQ diagnostic passport"
    )
    ap.add_argument("--volumes", required=True, help="ScrollQ volumes.json")
    ap.add_argument("--root", required=True, help="exact volume root or unique substring")
    ap.add_argument("--coverage", default=None, help="optional ScrollQ coverage.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    volumes = json.loads(Path(args.volumes).read_text(encoding="utf-8"))
    volume = _select_volume(volumes, args.root)
    coverage_map = (
        json.loads(Path(args.coverage).read_text(encoding="utf-8"))
        if args.coverage
        else {}
    )
    coverage = coverage_map.get(volume.get("root")) if coverage_map else None
    passport = build_passport(volume, coverage)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(passport, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
