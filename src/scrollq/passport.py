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
        "scroliq": "partial",
    },
    {
        "id": "fiber-connectivity",
        "stage": "unwrapping",
        "challenge": "Trace fewer fibers correctly with reliable long-range connectivity.",
        "scroliq": "planned",
    },
    {
        "id": "winding-annotations",
        "stage": "unwrapping",
        "challenge": "Create, validate, and prioritize local winding constraints for global spiral fitting.",
        "scroliq": "partial",
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
        "scroliq": "partial",
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


def _scan_stage(
    volume: dict[str, Any], scan_map: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not volume.get("ok"):
        return {
            "status": "blocked",
            "open_problem": "scan-diagnostics",
            "reason": volume.get("error", "volume could not be scored"),
        }

    sampling = dict(volume.get("sampling") or {})
    metrics = dict(volume.get("metrics") or {})
    components = dict(volume.get("components") or {})
    stage = {
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
            "The legacy ScrolIQ score is sparse whole-volume triage. Spatial "
            "diagnostics, when supplied, remain sampled observations rather than "
            "a claim that every voxel has been characterized."
        ),
    }
    if scan_map is None:
        stage["spatial_map"] = {
            "status": "unknown",
            "reason": "no spatial scan-diagnostic artifact was supplied",
        }
    elif scan_map.get("root") != volume.get("root"):
        stage["spatial_map"] = {
            "status": "excluded",
            "reason": "spatial scan artifact names a different volume root",
        }
    elif scan_map.get("diagnostic") != "spatial-scan-map":
        stage["spatial_map"] = {
            "status": "excluded",
            "reason": "artifact is not a ScrolIQ spatial-scan-map",
        }
    else:
        stage["spatial_map"] = {
            "status": "measured" if scan_map.get("ok") else "partial",
            "coordinate_space": scan_map.get("coordinate_space"),
            "sampling": scan_map.get("sampling", {}),
            "metric_distribution": scan_map.get("metric_distribution", {}),
        }
    return stage


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


def _winding_stage(
    volume_root: str,
    audit: dict[str, Any] | None,
) -> dict[str, Any]:
    if audit is None:
        return {
            "status": "unknown",
            "open_problem": "winding-annotations",
            "reason": "no winding-annotation audit was supplied",
        }
    if audit.get("diagnostic") != "winding-annotation-audit":
        return {
            "status": "excluded",
            "open_problem": "winding-annotations",
            "reason": "artifact is not a ScrolIQ winding-annotation-audit",
        }

    audit_root = audit.get("volume_root")
    if not isinstance(audit_root, str) or not audit_root:
        return {
            "status": "excluded",
            "open_problem": "winding-annotations",
            "reason": (
                "winding audit has no exact volume_root binding; rerun "
                "scroliq-winding with --volume-root"
            ),
        }
    if audit_root != volume_root:
        return {
            "status": "excluded",
            "open_problem": "winding-annotations",
            "reason": "winding audit names a different volume root",
        }

    audit_status = audit.get("status")
    if audit_status not in {"pass", "partial", "fail"}:
        return {
            "status": "excluded",
            "open_problem": "winding-annotations",
            "reason": f"unsupported winding audit status: {audit_status!r}",
        }

    stage_status = "blocked" if audit_status == "fail" else "partial"
    result = {
        "status": stage_status,
        "open_problem": "winding-annotations",
        "audit_status": audit_status,
        "present_roles": list(audit.get("present_roles") or []),
        "missing_roles": list(audit.get("missing_roles") or []),
        "totals": dict(audit.get("totals") or {}),
        "error_count": int(audit.get("error_count") or 0),
        "warning_count": int(audit.get("warning_count") or 0),
        "axial_coverage": dict(audit.get("axial_coverage") or {}),
        "limitation": (
            "A passing input audit establishes file/schema/role/provenance checks "
            "and descriptive axial coverage only. It does not establish CT support, "
            "patch attachment, winding-graph consistency, or spiral-fit accuracy."
        ),
    }
    if audit_status == "fail":
        result["reason"] = "winding annotation inputs failed the structural audit"
    return result



def _mesh_stage(
    volume_root: str,
    audit: dict[str, Any] | None,
) -> dict[str, Any]:
    if audit is None:
        return {
            "status": "unknown",
            "open_problem": "mesh-connectivity",
            "reason": "no volume-bound TIFXYZ mesh audit was supplied",
        }
    if audit.get("diagnostic") != "tifxyz-mesh-audit":
        return {
            "status": "excluded",
            "open_problem": "mesh-connectivity",
            "reason": "artifact is not a ScrolIQ tifxyz-mesh-audit",
        }

    audit_root = audit.get("volume_root")
    if not isinstance(audit_root, str) or not audit_root:
        return {
            "status": "excluded",
            "open_problem": "mesh-connectivity",
            "reason": "mesh audit has no exact volume_root binding; rerun scroliq-mesh with --volume-root",
        }
    if audit_root != volume_root:
        return {
            "status": "excluded",
            "open_problem": "mesh-connectivity",
            "reason": "mesh audit names a different volume root",
        }

    audit_status = audit.get("status")
    if audit_status not in {"pass", "partial", "fail"}:
        return {
            "status": "excluded",
            "open_problem": "mesh-connectivity",
            "reason": f"unsupported mesh audit status: {audit_status!r}",
        }

    result = {
        "status": "blocked" if audit_status == "fail" else "partial",
        "open_problem": "mesh-connectivity",
        "audit_status": audit_status,
        "tifxyz_path": audit.get("tifxyz_path"),
        "grid": dict(audit.get("grid") or {}),
        "bbox": dict(audit.get("bbox") or {}),
        "spacing": dict(audit.get("spacing") or {}),
        "quads": dict(audit.get("quads") or {}),
        "self_intersection": dict(audit.get("self_intersection") or {}),
        "findings": list(audit.get("findings") or []),
        "error_count": int(audit.get("error_count") or 0),
        "warning_count": int(audit.get("warning_count") or 0),
        "limitation": (
            (
                "A passing mesh audit establishes TIFXYZ structure, validity/topology, "
                "metadata, local spacing, normal continuity, flattening-distortion checks, "
                "and a validated VC3D transverse self-intersection census under its recorded "
                "parameters. It does not establish CT support or correct winding identity."
            )
            if (audit.get("self_intersection") or {}).get("status") == "pass"
            else (
                "A passing mesh audit establishes TIFXYZ structure, validity/topology, "
                "metadata, local spacing, normal continuity, and flattening-distortion checks only. "
                "It does not establish CT support, correct winding identity, or freedom from "
                "nonlocal self-intersections."
            )
        ),
    }
    if audit_status == "fail":
        result["reason"] = "TIFXYZ mesh failed structural or geometry audit checks"
    return result


def _ink_stage(
    volume_root: str,
    audit: dict[str, Any] | None,
) -> dict[str, Any]:
    if audit is None:
        return {
            "status": "unknown",
            "open_problem": "ink-reliability",
            "reason": "no volume-bound ink evidence audit was supplied",
        }
    if audit.get("diagnostic") != "ink-evidence-audit":
        return {
            "status": "excluded",
            "open_problem": "ink-reliability",
            "reason": "artifact is not a ScrolIQ ink-evidence-audit",
        }

    audit_root = audit.get("volume_root")
    if not isinstance(audit_root, str) or not audit_root:
        return {
            "status": "excluded",
            "open_problem": "ink-reliability",
            "reason": "ink audit has no exact volume_root binding; rerun scroliq-ink-audit with --volume-root",
        }
    if audit_root != volume_root:
        return {
            "status": "excluded",
            "open_problem": "ink-reliability",
            "reason": "ink audit names a different volume root",
        }

    audit_status = audit.get("status")
    if audit_status not in {"pass", "partial", "fail"}:
        return {
            "status": "excluded",
            "open_problem": "ink-reliability",
            "reason": f"unsupported ink audit status: {audit_status!r}",
        }

    result = {
        "status": "blocked" if audit_status == "fail" else "partial",
        "open_problem": "ink-reliability",
        "audit_status": audit_status,
        "model": dict(audit.get("model") or {}),
        "leakage": dict(audit.get("leakage") or {}),
        "controls": dict(audit.get("controls") or {}),
        "runs": dict(audit.get("runs") or {}),
        "error_count": int(audit.get("error_count") or 0),
        "warning_count": int(audit.get("warning_count") or 0),
        "limitation": (
            "A passing ink evidence audit establishes declared train/evaluation separation, "
            "checkpoint/seed provenance, and falsification-control coverage only. It does not "
            "establish that a prediction is ink or that the evidence generalizes across scrolls."
        ),
    }
    if audit_status == "fail":
        result["reason"] = "ink evidence failed leakage or provenance validation"
    return result


def _unknown_stage(open_problem: str, reason: str) -> dict[str, str]:
    return {"status": "unknown", "open_problem": open_problem, "reason": reason}


def build_passport(
    volume: dict[str, Any],
    coverage: dict[str, Any] | None = None,
    scan_map: dict[str, Any] | None = None,
    winding_audit: dict[str, Any] | None = None,
    mesh_audit: dict[str, Any] | None = None,
    ink_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one evidence-preserving diagnostic passport from current artifacts."""
    root = str(volume.get("root", ""))
    stages = {
        "data": _data_stage(volume),
        "scan": _scan_stage(volume, scan_map),
        "surface": _unknown_stage(
            "surface-topology",
            "no surface-prediction or surface-support diagnostic was supplied",
        ),
        "mesh": _mesh_stage(root, mesh_audit),
        "fibers": _unknown_stage(
            "fiber-connectivity", "no fiber tracing evidence was supplied"
        ),
        "winding": _winding_stage(root, winding_audit),
        "spiral": _unknown_stage(
            "spiral-fitting", "no spiral fit or constraint evaluation was supplied"
        ),
        "labels": _label_stage(coverage),
        "ink": _ink_stage(root, ink_audit),
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

    if stages["scan"].get("spatial_map", {}).get("status") == "unknown":
        actions.append(
            {
                "priority": "next-evidence",
                "action": "run scroliq-scan-map so local scan variation is coordinate-traceable",
                "open_problem": "scan-diagnostics",
            }
        )

    winding_status = stages["winding"]["status"]
    if winding_status in {"unknown", "excluded"}:
        actions.append(
            {
                "priority": "next-evidence",
                "action": (
                    "run scroliq-winding with the exact --volume-root before "
                    "using winding annotations as fit evidence"
                ),
                "open_problem": "winding-annotations",
            }
        )
    elif winding_status == "blocked":
        actions.append(
            {
                "priority": "high",
                "action": "repair winding annotation audit errors before spiral fitting",
                "open_problem": "winding-annotations",
            }
        )
    else:
        fit_window = stages["winding"].get("axial_coverage", {}).get("fit_window")
        empty_bins = list((fit_window or {}).get("empty_bins") or [])
        if empty_bins:
            actions.append(
                {
                    "priority": "next-evidence",
                    "action": (
                        "review or add verified winding constraints in empty axial "
                        f"coverage bins {empty_bins}; coverage is only a prioritization proxy"
                    ),
                    "open_problem": "winding-annotations",
                }
            )
        else:
            actions.append(
                {
                    "priority": "next-evidence",
                    "action": (
                        "advance winding evidence to patch attachment, graph consistency, "
                        "and held-out spiral-fit evaluation"
                    ),
                    "open_problem": "winding-annotations",
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

    mesh_status = stages["mesh"]["status"]
    if mesh_status in {"unknown", "excluded"}:
        actions.append(
            {
                "priority": "next-evidence",
                "action": "run scroliq-mesh with the exact --volume-root before trusting TIFXYZ geometry",
                "open_problem": "mesh-connectivity",
            }
        )
    elif mesh_status == "blocked":
        actions.append(
            {
                "priority": "high",
                "action": "repair TIFXYZ structural or geometry audit errors before flattening/render interpretation",
                "open_problem": "mesh-connectivity",
            }
        )
    elif stages["mesh"].get("audit_status") == "partial":
        actions.append(
            {
                "priority": "high",
                "action": "review Mesh IQ findings before using this surface downstream",
                "open_problem": "mesh-connectivity",
            }
        )
    else:
        selfcross_status = (
            stages["mesh"].get("self_intersection") or {}
        ).get("status")
        if selfcross_status == "pass":
            action = "add CT-support and sheet-identity evidence to the mesh"
        else:
            action = (
                "add CT-support and sheet-identity evidence, and run VC3D "
                "vc_tifxyz_selfcross for nonlocal transverse-intersection evidence"
            )
        actions.append(
            {
                "priority": "next-evidence",
                "action": action,
                "open_problem": "mesh-connectivity",
            }
        )

    ink_status = stages["ink"]["status"]
    if ink_status in {"unknown", "excluded"}:
        actions.append(
            {
                "priority": "next-evidence",
                "action": "run scroliq-ink-audit with the exact --volume-root before treating ink output as evidence",
                "open_problem": "ink-reliability",
            }
        )
    elif ink_status == "blocked":
        actions.append(
            {
                "priority": "high",
                "action": "resolve train/evaluation leakage or ink-evidence provenance errors",
                "open_problem": "ink-reliability",
            }
        )
    elif stages["ink"].get("audit_status") == "partial":
        actions.append(
            {
                "priority": "high",
                "action": "complete missing held-out or falsification controls before interpreting ink output",
                "open_problem": "ink-reliability",
            }
        )
    else:
        actions.append(
            {
                "priority": "next-evidence",
                "action": "attach measured perturbation stability and cross-scroll validation to the ink evidence",
                "open_problem": "ink-reliability",
            }
        )

    actions.append(
        {
            "priority": "next-evidence",
            "action": "run spatial surface-support/topology diagnostics on released predictions or tifxyz",
            "open_problem": "surface-topology",
        }
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
            "surface, mesh, winding geometry, spiral, label-localization, fiber, or ink state remains unknown."
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
    ap.add_argument("--volumes", required=True, help="ScrolIQ volumes.json")
    ap.add_argument("--root", required=True, help="exact volume root or unique substring")
    ap.add_argument("--coverage", default=None, help="optional ScrolIQ coverage.json")
    ap.add_argument("--scan-map", default=None, help="optional ScrolIQ spatial scan map")
    ap.add_argument(
        "--winding-audit",
        default=None,
        help="optional volume-bound scroliq-winding JSON artifact",
    )
    ap.add_argument("--mesh-audit", default=None, help="optional volume-bound scroliq-mesh JSON artifact")
    ap.add_argument("--ink-audit", default=None, help="optional volume-bound scroliq-ink-audit JSON artifact")
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
    scan_map = (
        json.loads(Path(args.scan_map).read_text(encoding="utf-8"))
        if args.scan_map
        else None
    )
    winding_audit = (
        json.loads(Path(args.winding_audit).read_text(encoding="utf-8"))
        if args.winding_audit
        else None
    )
    mesh_audit = (
        json.loads(Path(args.mesh_audit).read_text(encoding="utf-8"))
        if args.mesh_audit
        else None
    )
    ink_audit = (
        json.loads(Path(args.ink_audit).read_text(encoding="utf-8"))
        if args.ink_audit
        else None
    )
    passport = build_passport(
        volume,
        coverage=coverage,
        scan_map=scan_map,
        winding_audit=winding_audit,
        mesh_audit=mesh_audit,
        ink_audit=ink_audit,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(passport, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
