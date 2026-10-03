#!/usr/bin/env python3
"""Regenerate the 2026-10-03 Grand Prize target-freeze baseline.

This script intentionally uses only frozen, committed evidence. It verifies the
Git blob SHA-1 of every source before deriving candidate evidence, target-gate
inputs/reports, and the cohort blocker census.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scrollq.target_gate import evaluate_target_gate

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
AS_OF = "2026-10-03"

SOURCES = {
    "candidate_pool": (
        ROOT / "artifacts/2026-09-30-grand-prize-qualifier/geometry_candidate_pool.json",
        "447174e491159c5ac84f5e6656bf50317faf8dbf",
    ),
    "split_0800": (
        ROOT / "artifacts/2026-09-30-grand-prize-qualifier/pherc0800_geometry_split.json",
        "86dd19ffa63e1db6dc610b30936b341aa4504591",
    ),
    "split_0813": (
        ROOT / "artifacts/2026-09-30-grand-prize-qualifier/pherc0813_geometry_split.json",
        "eb9d999c57ef84536b19e50a6e3cf4fd50ca590b",
    ),
    "mesh_crosscut": (
        ROOT / "artifacts/2026-10-02-grand-prize-mesh-crosscut/summary.json",
        "f3af8a35b43aeb959dadeb648b9f4d4cdec5bfb2",
    ),
}

VOLUME_ROOTS = {
    "PHerc0800": (
        "https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0800/"
        "volumes/20250521135224-8.640um-1.2m-116keV-masked.zarr"
    ),
    "PHerc0813": (
        "https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0813/"
        "volumes/20250821151723-9.362um-1.2m-113keV-masked.zarr"
    ),
    "PHerc1447": (
        "https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc1447/"
        "volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr"
    ),
}

UNKNOWN = {
    "input_integrity": (
        "The frozen baseline sources do not include a target-specific ZPA report "
        "with integrity PASS and source attestation for this exact CT input."
    ),
    "ink_validation": (
        "The frozen baseline sources do not include a spatially disjoint "
        "target-specific ink-validation manifest with checkpoint, seed, "
        "evaluated-array hashes, and falsification controls."
    ),
    "vc3d_handoff": (
        "The frozen baseline sources do not include a target-specific VC3D "
        "load/handoff demonstration for these exact surface or review artifacts."
    ),
}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(\n        b"blob " + str(len(data)).encode("ascii") + b"\\0" + data\n    ).hexdigest()


def _read_source(name: str) -> dict[str, Any]:
    path, expected = SOURCES[name]
    raw = path.read_bytes()
    actual = _git_blob_sha1(raw)
    if actual != expected:
        raise RuntimeError(
            f"frozen source drift for {path.relative_to(ROOT)}: "
            f"{actual} != {expected}"
        )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def _source_record(name: str) -> dict[str, str]:
    path, sha = SOURCES[name]
    return {"path": path.relative_to(ROOT).as_posix(), "git_blob_sha1": sha}


def _crosscut_row(crosscut: dict[str, Any], scroll: str) -> dict[str, Any]:
    rows = [
        row for row in crosscut.get("targets", [])
        if isinstance(row, dict) and row.get("scroll") == scroll
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected one mesh cross-cut row for {scroll}")
    return rows[0]


def _surface_observations(
    scroll: str, pool_target: dict[str, Any], crosscut_row: dict[str, Any]
) -> dict[str, Any]:
    tiers = crosscut_row.get("tier_counts") or {}
    if scroll in {"PHerc0800", "PHerc0813"}:
        result = {
            "locked_candidates": len(pool_target.get("locked_candidates") or []),
            "bounds_complete": int(pool_target.get("bounds_complete") or 0),
            "atlas_total_meshes": int(pool_target.get("atlas_total_meshes") or 0),
            "public_exact_meshes_audited": int(
                crosscut_row.get("exact_volume_meshes_audited") or 0
            ),
            "public_mesh_tiers": {
                "clean": int(tiers.get("clean") or 0),
                "review": int(tiers.get("review") or 0),
                "multi-defect": int(tiers.get("multi-defect") or 0),
            },
        }
        result["boundary"] = (
            "Candidate and local mesh evidence do not prove correct sheet "
            "identity, full recto coverage, or readable ink."
            if scroll == "PHerc0800"
            else "The foothold comes from the frozen atlas candidate pool, not an "
                 "official public-segment mesh census; it does not prove sheet "
                 "identity or recto coverage."
        )
        return result
    return {
        "locked_candidates": int(pool_target.get("official_segment_count") or 0),
        "bounds_complete": 0,
        "bounds_status": pool_target.get("bounds_status"),
        "official_segment_count": int(pool_target.get("official_segment_count") or 0),
        "public_exact_meshes_audited": int(
            crosscut_row.get("exact_volume_meshes_audited") or 0
        ),
        "public_mesh_tiers": {
            "clean": int(tiers.get("clean") or 0),
            "review": int(tiers.get("review") or 0),
            "multi-defect": int(tiers.get("multi-defect") or 0),
        },
        "boundary": (
            "Every audited exact-volume segment has at least one Mesh IQ review "
            "finding; these are review cues, not proof that the surfaces are unusable."
        ),
    }


def _heldout_observations(split_doc: dict[str, Any]) -> dict[str, Any]:
    split = split_doc.get("split")
    if not isinstance(split, dict):
        raise RuntimeError("split artifact is missing split object")
    return {
        "state": "pass",
        "fit_candidates": int(split["fit_candidates"]),
        "held_out_candidates": int(split["held_out_candidates"]),
        "held_out_windows": list(split["held_out_windows"]),
        "core_overlap_check": split["core_overlap_check"],
        "minimum_axial_gap_between_any_locked_cores_slices": int(
            split["minimum_axial_gap_between_any_locked_cores_slices"]
        ),
        "uses_quality_or_ink": bool(split["uses_quality_or_ink"]),
    }


def _evidence(
    scroll: str,
    pool: dict[str, Any],
    crosscut: dict[str, Any],
    split: dict[str, Any] | None,
) -> dict[str, Any]:
    target = pool["targets"][scroll]
    sources = [_source_record("candidate_pool"), _source_record("mesh_crosscut")]
    if scroll == "PHerc0800":
        sources.append(_source_record("split_0800"))
    elif scroll == "PHerc0813":
        sources.append(_source_record("split_0813"))

    if split is not None:
        heldout = {
            "state": "pass",
            "claim": (
                "A geometry-only fit/held-out split was frozen before visual or "
                "ink screening, with failed candidates retained by protocol."
            ),
            "observations": _heldout_observations(split),
        }
    else:
        reason = (
            "The frozen candidate pool records PHerc1447 centroid/bounds extraction "
            "as pending, so a comparable geometry-only held-out split has not been "
            "frozen in the baseline sources."
        )
        heldout = {
            "state": "unknown",
            "claim": (
                "A comparable geometry-only held-out split is not yet frozen in "
                "the baseline evidence."
            ),
            "reason": reason,
        }

    return {
        "schema_version": 1,
        "as_of": AS_OF,
        "scroll": scroll,
        "volume_id": target["prize_volume_id"],
        "sources": sources,
        "claims": {
            "surface_foothold": {
                "state": "pass",
                "claim": (
                    "At least one exact-volume surface or mesh region exists in "
                    "the frozen evidence with geometry provenance sufficient to "
                    "define a proof candidate."
                ),
                "observations": _surface_observations(
                    scroll, target, _crosscut_row(crosscut, scroll)
                ),
            },
            "heldout_geometry": heldout,
        },
        "claim_boundary": (
            "This derived record establishes only the prerequisite evidence "
            "described above. It is not a readability, correct-sheet, full-recto, "
            "ink, or Grand Prize-success claim."
        ),
    }


def _gate_input(
    scroll: str, evidence: dict[str, Any], evidence_sha256: str
) -> dict[str, Any]:
    volume_id = evidence["volume_id"]
    artifact = {
        "kind": "target-baseline-evidence",
        "uri": f"artifacts/2026-10-03-target-freeze-baseline/{scroll}.evidence.json",
        "sha256": evidence_sha256,
        "volume_id": volume_id,
    }
    prerequisites = {
        "input_integrity": {
            "state": "unknown",
            "rationale": UNKNOWN["input_integrity"],
            "artifacts": [],
        },
        "surface_foothold": {
            "state": "pass",
            "rationale": (
                "Frozen exact-volume geometry evidence provides at least one "
                "proof-candidate surface or mesh foothold."
            ),
            "artifacts": [
                {
                    **artifact,
                    "claim": (
                        "Derived exact-volume evidence for the surface-foothold "
                        "prerequisite."
                    ),
                }
            ],
        },
        "ink_validation": {
            "state": "unknown",
            "rationale": UNKNOWN["ink_validation"],
            "artifacts": [],
        },
        "vc3d_handoff": {
            "state": "unknown",
            "rationale": UNKNOWN["vc3d_handoff"],
            "artifacts": [],
        },
    }
    heldout = evidence["claims"]["heldout_geometry"]
    prerequisites["heldout_geometry"] = (
        {
            "state": "pass",
            "rationale": (
                "A geometry-only fit/held-out split is frozen with disjoint "
                "evaluation cores and without quality or ink selection."
            ),
            "artifacts": [
                {
                    **artifact,
                    "claim": (
                        "Derived exact-volume evidence for the held-out-geometry "
                        "prerequisite."
                    ),
                }
            ],
        }
        if heldout["state"] == "pass"
        else {"state": "unknown", "rationale": heldout["reason"], "artifacts": []}
    )
    return {
        "schema_version": 1,
        "as_of": AS_OF,
        "candidate": {
            "scroll": scroll,
            "volume_id": volume_id,
            "volume_root": VOLUME_ROOTS[scroll],
        },
        "prerequisites": prerequisites,
    }


def main() -> None:
    pool = _read_source("candidate_pool")
    crosscut = _read_source("mesh_crosscut")
    splits = {
        "PHerc0800": _read_source("split_0800"),
        "PHerc0813": _read_source("split_0813"),
        "PHerc1447": None,
    }
    reports: dict[str, dict[str, Any]] = {}
    for scroll in ("PHerc0800", "PHerc0813", "PHerc1447"):
        evidence = _evidence(scroll, pool, crosscut, splits[scroll])
        evidence_bytes = _json_bytes(evidence)
        (OUT / f"{scroll}.evidence.json").write_bytes(evidence_bytes)
        gate_input = _gate_input(scroll, evidence, _sha256(evidence_bytes))
        (OUT / f"{scroll}.input.json").write_bytes(_json_bytes(gate_input))
        report = evaluate_target_gate(gate_input)
        reports[scroll] = report
        (OUT / f"{scroll}.gate.json").write_bytes(_json_bytes(report))

    summary = {
        "schema_version": 1,
        "as_of": AS_OF,
        "diagnostic": "grand-prize-target-freeze-baseline",
        "cohort": ["PHerc0800", "PHerc0813", "PHerc1447"],
        "selection_rule": (
            "Historical first-wave hypotheses are evaluated only as a frozen "
            "baseline cohort; this artifact does not rank them or select a target."
        ),
        "targets": [
            {
                "scroll": scroll,
                "volume_id": pool["targets"][scroll]["prize_volume_id"],
                "status": reports[scroll]["status"],
                "blocking_checks": reports[scroll]["blocking_checks"],
                "unknown_checks": reports[scroll]["unknown_checks"],
                "gate_report": f"{scroll}.gate.json",
            }
            for scroll in ("PHerc0800", "PHerc0813", "PHerc1447")
        ],
        "shared_unknown_checks": [
            "input_integrity",
            "ink_validation",
            "vc3d_handoff",
        ],
        "next_action": {
            "stage": "input_integrity",
            "reason": (
                "It is unknown for every cohort member and the probe protocol "
                "says geometry or ink evidence is not interpretable until the "
                "exact consumed inputs pass integrity/provenance checks."
            ),
            "required_output": (
                "One exact-volume ZPA report with integrity PASS and source "
                "attestation for each candidate CT and any geometry inputs actually "
                "consumed."
            ),
        },
        "claim_boundary": (
            "All three candidates remain provisional. This is a blocker census, "
            "not a recommendation, ranking, readability estimate, or Grand "
            "Prize-success prediction."
        ),
    }
    (OUT / "cohort.json").write_bytes(_json_bytes(summary))


if __name__ == "__main__":
    main()
