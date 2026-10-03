"""Normalize ScrollFiesta release evidence without inflating its claims.

ScrollFiesta publishes a machine-readable release ledger for its public sheet
assembler. This adapter preserves the producer's qualification state, geometry
metrics, CT-bake coverage, build checks, and hashes in a ScrolIQ-shaped evidence
record. It deliberately does not infer whole-scroll, winding, ink, legibility,
or Grand Prize readiness from a local geometry result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DIAGNOSTIC = "scrollfiesta-release-evidence"
SUPPORTED_SCHEMA = "scrollfiesta-public-release-check-v1"
DEFAULT_REPOSITORY = "https://github.com/Hob3rMallow/scrollfiesta_public"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finding(code: str, severity: str, message: str, **evidence: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if evidence:
        row["evidence"] = evidence
    return row


def normalize_scrollfiesta_release(
    report: dict[str, Any],
    *,
    expected_scroll: str | None = None,
    expected_region: str | None = None,
    repository: str = DEFAULT_REPOSITORY,
    commit: str | None = None,
) -> dict[str, Any]:
    """Convert one ScrollFiesta public release ledger into conservative evidence."""

    source = {
        "tool": "ScrollFiesta",
        "repository": repository,
        "commit": commit,
        "schema": report.get("schema"),
        "date": report.get("date"),
    }
    scope = {
        "scroll": report.get("scroll"),
        "region": report.get("region"),
        "mesh_pile": report.get("mesh_pile"),
        "cube_count": report.get("cube_count"),
        "chunk_size": report.get("chunk_size"),
        "bounds_zyx_half_open": report.get("bounds_zyx_half_open"),
    }
    base = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic": DIAGNOSTIC,
        "source": source,
        "scope": scope,
    }

    if report.get("schema") != SUPPORTED_SCHEMA:
        return {
            **base,
            "status": "excluded",
            "reason": f"unsupported ScrollFiesta release schema: {report.get('schema')!r}",
            "claims": {},
            "findings": [
                _finding(
                    "SCROLLFIESTA_SCHEMA_UNSUPPORTED",
                    "error",
                    "The producer ledger schema is not supported; no measurements were imported.",
                )
            ],
            "grand_prize_scope": {
                "status": "not-established",
                "reasons": ["No producer measurements were imported."],
            },
        }

    mismatches: list[str] = []
    if expected_scroll is not None and report.get("scroll") != expected_scroll:
        mismatches.append(
            f"scroll {report.get('scroll')!r} != expected {expected_scroll!r}"
        )
    if expected_region is not None and report.get("region") != expected_region:
        mismatches.append(
            f"region {report.get('region')!r} != expected {expected_region!r}"
        )
    if mismatches:
        return {
            **base,
            "status": "excluded",
            "reason": "; ".join(mismatches),
            "claims": {},
            "findings": [
                _finding(
                    "SCROLLFIESTA_SCOPE_MISMATCH",
                    "error",
                    "The ledger does not match the requested scroll/region; no measurements were imported.",
                    mismatches=mismatches,
                )
            ],
            "grand_prize_scope": {
                "status": "not-established",
                "reasons": ["The producer ledger is out of the requested evaluation scope."],
            },
        }

    audit = report.get("audit") if isinstance(report.get("audit"), dict) else {}
    preview = report.get("preview") if isinstance(report.get("preview"), dict) else {}
    validation = (
        report.get("validation") if isinstance(report.get("validation"), dict) else {}
    )
    coverage = (
        preview.get("coverage") if isinstance(preview.get("coverage"), dict) else {}
    )
    configuration = (
        report.get("configuration")
        if isinstance(report.get("configuration"), dict)
        else {}
    )

    findings: list[dict[str, Any]] = []
    audit_complete = audit.get("audit_complete") is True
    if not audit_complete:
        findings.append(
            _finding(
                "SCROLLFIESTA_AUDIT_INCOMPLETE",
                "error",
                "The producer does not mark its geometry audit complete.",
            )
        )
    if audit.get("geometry_qualified") is not True:
        findings.append(
            _finding(
                "SCROLLFIESTA_GEOMETRY_UNQUALIFIED",
                "warning",
                "The producer explicitly marks this geometry as unqualified.",
            )
        )
    if audit.get("whole_scroll_qualified") is not True:
        findings.append(
            _finding(
                "SCROLLFIESTA_WHOLE_SCROLL_UNQUALIFIED",
                "warning",
                "The producer explicitly does not qualify this result as a whole-scroll result.",
            )
        )
    if audit.get("source_preserved") is False:
        findings.append(
            _finding(
                "SCROLLFIESTA_SOURCE_NOT_PRESERVED",
                "error",
                "The producer reports that source geometry was not preserved.",
            )
        )

    measured_coverage = audit.get("coverage")
    minimum_coverage = audit.get("minimum_coverage")
    if isinstance(measured_coverage, (int, float)) and isinstance(
        minimum_coverage, (int, float)
    ):
        if measured_coverage < minimum_coverage:
            findings.append(
                _finding(
                    "SCROLLFIESTA_COVERAGE_BELOW_PRODUCER_GATE",
                    "warning",
                    "Represented source-area coverage is below the producer's own qualification threshold.",
                    coverage=measured_coverage,
                    minimum_coverage=minimum_coverage,
                )
            )

    overlaps = audit.get("overlapping_triangle_pairs")
    if isinstance(overlaps, int) and overlaps > 0:
        findings.append(
            _finding(
                "SCROLLFIESTA_OVERLAPS_REMAIN",
                "warning",
                "The producer audit reports remaining overlapping triangle pairs.",
                overlapping_triangle_pairs=overlaps,
            )
        )

    unresolved = audit.get("unresolved_seams")
    if isinstance(unresolved, int) and unresolved > 0:
        findings.append(
            _finding(
                "SCROLLFIESTA_UNRESOLVED_SEAMS",
                "warning",
                "The producer audit reports unresolved seam obligations.",
                unresolved_seams=unresolved,
            )
        )

    if coverage and coverage.get("complete") is not True:
        findings.append(
            _finding(
                "SCROLLFIESTA_CT_BAKE_INCOMPLETE",
                "warning",
                "The CT bake does not cover the complete declared source volume/cube set.",
                expected_chunks=coverage.get("expected_chunks"),
                loaded_chunks=coverage.get("loaded_chunks"),
                missing_chunks=coverage.get("missing_chunks"),
                faces_unpainted_missing_raw=coverage.get("faces_unpainted_missing_raw"),
            )
        )

    claims = {
        "producer_qualification": {
            "audit_complete": audit.get("audit_complete"),
            "geometry_qualified": audit.get("geometry_qualified"),
            "whole_scroll_qualified": audit.get("whole_scroll_qualified"),
            "qualification_contract": audit.get("qualification_contract"),
            "minimum_coverage": audit.get("minimum_coverage"),
            "minimum_source_region_coherence": audit.get(
                "minimum_source_region_coherence"
            ),
            "boundary": report.get("boundary"),
        },
        "source_accounting": {
            key: audit.get(key)
            for key in (
                "source_preserved",
                "source_faces",
                "accounted_source_faces",
                "represented_source_faces",
                "absent_source_faces",
                "multiply_owned_source_faces",
                "foreign_faces",
                "altered_source_vertices",
                "source_area",
                "represented_area",
                "excluded_area",
                "unplaced_area",
                "missing_area",
                "placed_charts",
                "unplaced_charts",
                "excluded_charts",
            )
        },
        "geometry": {
            key: audit.get(key)
            for key in (
                "coverage",
                "audited_faces",
                "invalid_faces",
                "strict_bad_faces",
                "bad_metric_charts",
                "sigma_min",
                "sigma_max",
                "overlapping_triangle_pairs",
                "self_overlapping_pairs",
                "overlap_area_sum",
                "obligations",
                "passing_seams",
                "unresolved_seams",
                "repair_obligations",
                "passing_repair_seams",
                "unresolved_repair_seams",
                "continuity_components",
                "source_region_coherence",
                "unresolved_present_repair_seams",
                "unresolved_missing_repair_seams",
                "boundary_length_vox",
                "stitched_boundary_length_vox",
                "border_length_vox",
                "border_per_sqrt_area",
            )
        },
        "ct_texture": {
            "status": (
                "measured"
                if coverage.get("complete") is True
                else "partial"
            ),
            "source": preview.get("source"),
            "vmesh_sha256": preview.get("vmesh_sha256"),
            "raw_source": preview.get("raw_source"),
            "normal_range_vox": preview.get("normal_range_vox"),
            "normal_samples": preview.get("normal_samples"),
            "window_u8": preview.get("window_u8"),
            "raster_du": preview.get("raster_du"),
            "raster_dv": preview.get("raster_dv"),
            "bounded_void_fill_pixels": preview.get("bounded_void_fill_pixels"),
            "coverage": coverage,
            "grid": preview.get("grid"),
            "full_png_sha256": preview.get("full_png_sha256"),
            "figure": preview.get("figure"),
            "figure_sha256": preview.get("figure_sha256"),
        },
        "software_validation": dict(validation),
        "producer_hashes": {
            "source_decoded_sha256": audit.get("source_decoded_sha256"),
            "field_sha256": audit.get("field_sha256"),
            "obligations_sha256": audit.get("obligations_sha256"),
            "configuration_path": configuration.get("path"),
            "configuration_sha256_lf": configuration.get("sha256_lf"),
            "axis_path": configuration.get("axis_path"),
            "axis_sha256_lf": configuration.get("axis_sha256_lf"),
            "text_hash_rule": configuration.get("text_hash_rule"),
        },
    }

    gp_reasons = [
        "A local ScrollFiesta release ledger does not establish 100% recto coverage.",
        "It does not establish one submitted TIFXYZ mesh per full text column or sequential column traceability.",
        "It does not establish final submission images, 1 cm scale bars, or the full-scroll numbered banner.",
        "It does not establish letter-by-letter 70% per-column papyrological legibility.",
        "It does not establish ink-model training/prediction separation or held-out ink validation.",
        "It does not establish false-positive/hallucination controls for ink.",
        "It does not establish the final Docker/VC3D reproduction contract.",
    ]
    if audit.get("whole_scroll_qualified") is not True:
        gp_reasons.insert(
            0, "The producer explicitly does not qualify this artifact as a whole-scroll result."
        )
    if audit.get("geometry_qualified") is not True:
        gp_reasons.insert(
            0, "The producer explicitly marks the geometry as unqualified."
        )

    return {
        **base,
        "status": "measured" if audit_complete else "partial",
        "claims": claims,
        "findings": findings,
        "grand_prize_scope": {
            "status": "not-established",
            "reasons": gp_reasons,
        },
        "limitations": [
            (
                "All imported measurements are producer-reported. ScrolIQ preserves "
                "the release ledger but does not independently recompute the geometry."
            ),
            (
                "ScrollFiesta vmesh/source hashes are not treated as a content binding "
                "to a ScrolIQ TIFXYZ artifact unless a separate cross-format identity "
                "proof is supplied."
            ),
            (
                "A bounded regional result is never promoted to whole-scroll evidence, "
                "even if every local producer gate passes."
            ),
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Normalize a ScrollFiesta public release ledger into conservative ScrolIQ evidence"
    )
    ap.add_argument("--results", required=True, help="ScrollFiesta results.json")
    ap.add_argument("--expected-scroll", default=None)
    ap.add_argument("--expected-region", default=None)
    ap.add_argument("--repository", default=DEFAULT_REPOSITORY)
    ap.add_argument("--commit", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    source_path = Path(args.results)
    report = json.loads(source_path.read_text(encoding="utf-8"))
    evidence = normalize_scrollfiesta_release(
        report,
        expected_scroll=args.expected_scroll,
        expected_region=args.expected_region,
        repository=args.repository,
        commit=args.commit,
    )
    evidence["input"] = {
        "path": str(source_path),
        "sha256": _sha256(source_path),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        f"{evidence['status'].upper()} "
        f"{evidence['scope'].get('scroll')} {evidence['scope'].get('region')}: "
        f"findings={len(evidence.get('findings', []))} "
        f"grand_prize={evidence['grand_prize_scope']['status']}"
    )
    if evidence["status"] == "excluded":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
