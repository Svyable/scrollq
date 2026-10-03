#!/usr/bin/env python3
"""Derive exact-volume 2027 Grand Prize mesh evidence from committed artifacts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MESH = ROOT / "artifacts/2026-10-01-corpus-mesh-audit/summary.json"
MANIFEST = ROOT / "artifacts/2026-10-01-prize-targets/grand-prize-manifest.json"
OUT = Path(__file__).with_name("summary.json")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    mesh = load(MESH)
    manifest = load(MANIFEST)
    rows = mesh.get("rows", [])
    targets = []

    for target in manifest["targets"]:
        exact = [
            row for row in rows
            if row.get("scroll") == target["scroll"]
            and str(row.get("volume_id")) == str(target["volume_id"])
        ]
        tiers = Counter(row.get("tier") for row in exact)
        findings = Counter(
            finding for row in exact for finding in row.get("findings", [])
        )
        targets.append({
            "scroll": target["scroll"],
            "volume_id": str(target["volume_id"]),
            "official_public_segments": target.get("segments", 0),
            "exact_volume_meshes_audited": len(exact),
            "exact_volume_segments": len({row.get("segment") for row in exact}),
            "tier_counts": {
                "clean": tiers.get("clean", 0),
                "review": tiers.get("review", 0),
                "multi-defect": tiers.get("multi-defect", 0),
            },
            "finding_counts": dict(sorted(findings.items())),
            "segments": [{
                "segment": row.get("segment"),
                "tier": row.get("tier"),
                "findings": row.get("findings", []),
                "report": row.get("report"),
            } for row in exact],
        })

    with_meshes = [row for row in targets if row["exact_volume_meshes_audited"]]
    out = {
        "schema_version": 1,
        "diagnostic": "grand-prize-exact-volume-mesh-crosscut",
        "as_of": "2026-10-02",
        "status": "complete-for-committed-inputs",
        "rule": (
            "Only meshes registered to the exact 2027 Grand Prize volume_id count. "
            "Same-scroll meshes on other scans are excluded."
        ),
        "sources": {
            "prize_manifest": str(MANIFEST.relative_to(ROOT)),
            "mesh_corpus": str(MESH.relative_to(ROOT)),
        },
        "totals": {
            "eligible_targets": len(targets),
            "targets_with_exact_volume_mesh_evidence": len(with_meshes),
            "exact_volume_meshes_audited": sum(
                row["exact_volume_meshes_audited"] for row in with_meshes
            ),
            "exact_volume_segments": sum(
                row["exact_volume_segments"] for row in with_meshes
            ),
        },
        "targets": targets,
        "claim_boundary": [
            "This is a cross-cut of existing local mesh-geometry evidence, not a new mesh audit.",
            "A clean local mesh audit does not prove correct sheet identity, full recto coverage, or readability.",
            "A finding is a review candidate unless independently confirmed.",
            "Targets with zero published exact-volume meshes are evidence gaps, not failures.",
        ],
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
