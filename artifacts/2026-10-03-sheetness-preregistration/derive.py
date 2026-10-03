#!/usr/bin/env python3
"""Derive the frozen PHerc0800 sheetness campaign protocol from committed evidence.

This script deliberately emits no measured CT result. It selects the target,
primary mesh, control-candidate pool, and PHerc1447 geometry stress control
from artifacts that existed before the campaign was run.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("protocol.json")
SNAPSHOT_COMMIT = "7229030c18e9bb64363efe614b203d4183d96619"
CORPUS_SUMMARY = ROOT / "artifacts/2026-10-01-corpus-mesh-audit/summary.json"
PRIZE_MANIFEST = ROOT / "artifacts/2026-10-01-prize-targets/grand-prize-manifest.json"
REPORT_DIR = ROOT / "artifacts/2026-10-01-corpus-mesh-audit/reports"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def target(manifest: dict, scroll: str) -> dict:
    rows = [row for row in manifest["targets"] if row["scroll"] == scroll]
    if len(rows) != 1:
        raise SystemExit(f"expected exactly one prize target for {scroll}, got {len(rows)}")
    return rows[0]


def eligible_root(t: dict) -> str:
    voxel = f"{float(t['voxel_size_um']):.3f}"
    energy = int(float(t["energy_kev"]))
    return (
        f"{t['scroll']}/volumes/{t['volume_id']}-"
        f"{voxel}um-1.2m-{energy}keV-masked.zarr"
    )


def public_mesh_path(report: dict) -> str:
    prefix = "out/corpus-s3/"
    path = report["tifxyz_path"]
    if not path.startswith(prefix):
        raise SystemExit(f"unexpected corpus mesh path: {path}")
    return path[len(prefix):].rstrip("/")


def mesh_record(row: dict) -> dict:
    report_path = ROOT / "artifacts/2026-10-01-corpus-mesh-audit" / row["report"]
    report = load(report_path)
    if report.get("volume_root") != row.get("volume_root"):
        raise SystemExit(f"volume root drift in {row['report']}")
    if report.get("status") != row.get("status"):
        raise SystemExit(f"status drift in {row['report']}")
    return {
        "segment": row["segment"],
        "registered_volume_root": row["volume_root"],
        "public_tifxyz_path": public_mesh_path(report),
        "audit_report": str(report_path.relative_to(ROOT)),
        "audit_status": report["status"],
        "audit_findings": report.get("findings", []),
        "shape_yx": report["grid"]["shape_yx"],
        "observed_bbox_xyz": report["bbox"]["observed_bbox_xyz"],
        "coordinate_files": {
            name: {
                "sha256": report["provenance"][name]["sha256"],
                "bytes": report["provenance"][name]["bytes"],
            }
            for name in ("meta.json", "x.tif", "y.tif", "z.tif")
        },
    }


def main() -> None:
    summary = load(CORPUS_SUMMARY)
    manifest = load(PRIZE_MANIFEST)
    p800 = target(manifest, "PHerc0800")
    p1447 = target(manifest, "PHerc1447")

    p800_rows = sorted(
        [
            row
            for row in summary["rows"]
            if row["scroll"] == "PHerc0800"
            and row["volume_id"] == p800["volume_id"]
            and row["status"] == "pass"
            and row["tier"] == "clean"
            and not row["findings"]
        ],
        key=lambda row: row["segment"],
    )
    if len(p800_rows) != 6:
        raise SystemExit(f"expected six clean exact-volume PHerc0800 meshes, got {len(p800_rows)}")

    primary = mesh_record(p800_rows[0])
    controls = [mesh_record(row) for row in p800_rows[1:]]

    stress_id = summary["positive_control"]["segment"]
    stress_rows = [
        row
        for row in summary["rows"]
        if row["scroll"] == "PHerc1447"
        and row["volume_id"] == p1447["volume_id"]
        and row["segment"] == stress_id
    ]
    if len(stress_rows) != 1:
        raise SystemExit(f"expected one PHerc1447 stress-control row, got {len(stress_rows)}")
    stress = mesh_record(stress_rows[0])

    protocol = {
        "schema_version": 1,
        "kind": "scroliq-sheetness-realdata-preregistration",
        "campaign_id": "2026-10-03-pherc0800-sheetness-v1",
        "measurement_state": "not-run",
        "input_snapshot_commit": SNAPSHOT_COMMIT,
        "source_artifacts": {
            "grand_prize_manifest": str(PRIZE_MANIFEST.relative_to(ROOT)),
            "mesh_corpus_summary": str(CORPUS_SUMMARY.relative_to(ROOT)),
        },
        "target": {
            "scroll": p800["scroll"],
            "eligible_volume_id": p800["volume_id"],
            "voxel_size_um": p800["voxel_size_um"],
            "eligible_volume_root": eligible_root(p800),
            "ct_base_url": "https://vesuvius-challenge-open-data.s3.amazonaws.com",
            "primary_selection_rule": (
                "Among exact-volume PHerc0800 TIFXYZ rows that are status=pass, "
                "tier=clean, and have no findings in the frozen corpus audit, "
                "choose the lexicographically first segment ID."
            ),
            "primary_mesh": primary,
            "wrong_wrap_candidate_pool": controls,
        },
        "volume_context_gate": {
            "required": True,
            "reason": (
                "The frozen mesh audit records a community-uploads/forrest/volcomp "
                "registration root, while the prize CT is the top-level exact eligible "
                "S3 root. Same volume_id alone is not accepted as a coordinate-frame proof."
            ),
            "pass_if_either": [
                (
                    "the downloaded TIFXYZ meta.json identifies the exact eligible "
                    "volume_id in target_volume"
                ),
                (
                    "a separately hash-pinned volume-context artifact proves the "
                    "registered source and eligible CT share the required level-0 coordinate frame"
                ),
            ],
            "on_failure": "STOP; publish context as unbound and do not extract CT or score sheetness",
        },
        "wrong_wrap_gate": {
            "candidate_order": "ascending segment ID; measured selection uses the rule below, not manual choice",
            "coordinate_hashes_must_match_frozen_audit": True,
            "interior_vertex_rule": (
                "primary/control vertex must be valid and have valid +/-1 row and "
                "+/-1 column neighbours so a centered normal can be estimated"
            ),
            "nearest_vertex_distance_voxels": {"min_inclusive": 12.0, "max_inclusive": 96.0},
            "minimum_abs_normal_cosine": 0.8,
            "minimum_eligible_pairs": 4,
            "selection_rule": (
                "For each candidate mesh, compute the nearest interior control vertex "
                "for every interior primary vertex. Keep pairs meeting distance and "
                "normal-alignment gates. Select the candidate with the most eligible "
                "pairs; ties go to the lexicographically smaller segment ID."
            ),
            "on_failure": (
                "STOP as inconclusive; do not relabel a duplicate surface, distant "
                "background point, normal offset, or another scan as a wrong-wrap control"
            ),
        },
        "probe_selection": {
            "group_count": 4,
            "seed_rule": "smallest primary grid linear index among eligible pairs",
            "cluster_radius_voxels": 96.0,
            "selection_rule": (
                "Starting at the seed, keep eligible primary vertices within the "
                "cluster radius; sort by grid linear index and take the first four."
            ),
            "normal_offset_voxels": [-8.0, 8.0],
            "coordinate_rounding": "round half to nearest NumPy integer only after global probe coordinates are frozen",
            "cutout_padding_voxels": 12,
            "max_cutout_voxels": 2500000,
            "on_insufficient_groups_or_oversize": "STOP; do not alter thresholds or hand-pick another patch",
        },
        "sheetness_engine": {
            "tool": "scroliq-sheetness",
            "sigmas": [0.8, 1.2, 1.8],
            "beta": 0.5,
            "gamma": 0.1,
            "bright_object": True,
            "scale_objectness": False,
            "normalization": {"enabled": True, "lower_percentile": 1.0, "upper_percentile": 99.0},
            "write_normal": True,
            "stochastic": False,
            "seed": None,
        },
        "decision_rule": {
            "tool": "scroliq-sheetness-eval",
            "min_score_completeness": 1.0,
            "min_surface_win_fraction": 0.75,
            "min_median_margin": 0.0,
            "min_normal_completeness": 1.0,
            "min_median_abs_cosine": 0.7,
            "frozen_before_measurement": True,
        },
        "required_runtime_provenance": [
            "fresh ZPA PASS report for the exact eligible CT root with PRESENT source attestation",
            "scroliq-ct-cutout manifest for the exact global level-0 box",
            "hash-verified downloaded TIFXYZ coordinate files",
            "generated frozen probe spec before scroliq-sheetness-eval",
            "sheetness report/response/normal hashes",
        ],
        "geometry_stress_control": {
            "scroll": p1447["scroll"],
            "eligible_volume_id": p1447["volume_id"],
            "eligible_volume_root": eligible_root(p1447),
            "mesh": stress,
            "interpretation": (
                "This is a known multi-defect geometry control, not a presumed non-papyrus "
                "or low-sheetness control. A high physical sheetness response MUST NOT "
                "upgrade its Mesh IQ status or be interpreted as correct topology."
            ),
            "expected_sheetness_outcome": None,
        },
        "stop_rules": [
            "No real-data parameter or threshold may change after this protocol is committed.",
            "No substitute scan of PHerc0800 or PHerc1447 may be used.",
            "If volume context is unbound, stop rather than infer coordinate equivalence from the volume ID.",
            "If no wrong-wrap candidate satisfies the geometric gate, report the campaign inconclusive.",
            "If the frozen decision rule fails, publish FAIL; do not tune and rerun as v1.",
            "Horizon-path experiments remain blocked until this sheetness campaign has a valid measured result.",
        ],
        "claim_boundary": (
            "A PASS would establish only that a frozen Hessian sheetness field preferentially "
            "supports selected public mesh points over preregistered normal-offset and geometrically "
            "distinct nearby-surface controls on one exact Grand Prize CT. It would not prove sheet "
            "identity, winding correctness, recto completeness, ink, or readability."
        ),
    }
    OUT.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
