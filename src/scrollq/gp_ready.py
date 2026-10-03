"""Compose official-rule provenance validation with independent evidence.

The resulting verdict is intentionally three-state:
- READY: provenance eligibility passes and every required independent claim passes.
- BLOCKED: a rule/provenance check or explicit independent evidence check fails.
- UNKNOWN: provenance passes, but required independent evidence is incomplete.

This is a ScrolIQ pre-submission gate, not an official Scroll Prize decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .evidence_ledger import validate_evidence_ledger
from .provenance import validate_manifest


def evaluate_readiness(
    provenance_report: dict[str, Any],
    evidence_report: dict[str, Any],
) -> dict[str, Any]:
    provenance_ok = provenance_report.get("eligible") is True
    evidence_status = evidence_report.get("status")

    if not provenance_ok or evidence_status == "fail":
        status = "blocked"
    elif evidence_status == "pass":
        status = "ready"
    else:
        status = "unknown"

    blockers: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []

    for item in provenance_report.get("errors") or []:
        blockers.append(
            {
                "source": "provenance",
                "code": item.get("code"),
                "path": item.get("path"),
                "message": item.get("message"),
            }
        )
    for item in evidence_report.get("errors") or []:
        blockers.append(
            {
                "source": "independent-evidence",
                "code": item.get("code"),
                "path": item.get("path"),
                "message": item.get("message"),
            }
        )

    for claim in evidence_report.get("required_claims") or []:
        claim_status = claim.get("status")
        if claim_status == "fail":
            blockers.append(
                {
                    "source": "independent-evidence",
                    "code": "EVIDENCE_CLAIM_FAIL",
                    "path": claim.get("claim"),
                    "message": claim.get("reason"),
                }
            )
        elif claim_status != "pass":
            unknowns.append(
                {
                    "source": "independent-evidence",
                    "claim": claim.get("claim"),
                    "status": claim_status,
                    "message": claim.get("reason"),
                    "missing_mesh_ids": claim.get("missing_mesh_ids") or [],
                }
            )

    return {
        "validator": "scrollq.gp_ready",
        "schema_version": 1,
        "status": status,
        "ready": status == "ready",
        "provenance": {
            "eligible": provenance_report.get("eligible") is True,
            "graph_sha256": provenance_report.get("graph_sha256"),
            "error_count": int(provenance_report.get("error_count") or 0),
        },
        "independent_evidence": {
            "status": evidence_status,
            "graph_sha256": evidence_report.get("graph_sha256"),
            "error_count": int(evidence_report.get("error_count") or 0),
        },
        "blockers": blockers,
        "unknowns": unknowns,
        "limitation": (
            "READY means the package passed ScrolIQ's mechanical provenance "
            "checks and its current independent-evidence policy. It is not an "
            "official Scroll Prize eligibility or award decision and does not "
            "establish that 70% of preserved characters in a counted column "
            "are legible."
        ),
    }


def validate_readiness(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    root_dir: Path | None = None,
    provenance_manifest_sha256: str | None = None,
    evidence_ledger_sha256: str | None = None,
) -> dict[str, Any]:
    provenance_report = validate_manifest(
        manifest,
        root_dir=root_dir,
        manifest_sha256=provenance_manifest_sha256,
    )
    submission = manifest.get("submission") if isinstance(manifest, dict) else {}
    volume_id = submission.get("eligible_volume_id") if isinstance(submission, dict) else None
    raw_meshes = manifest.get("meshes") if isinstance(manifest, dict) else []
    mesh_ids = [
        str(item.get("id"))
        for item in raw_meshes
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    ]

    evidence_report = validate_evidence_ledger(
        ledger,
        expected_volume_id=volume_id if isinstance(volume_id, str) else None,
        expected_mesh_ids=mesh_ids,
        root_dir=root_dir,
        ledger_sha256=evidence_ledger_sha256,
        require_local_artifacts=True,
    )
    return evaluate_readiness(provenance_report, evidence_report)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Fail-closed 2027 Grand Prize pre-submission readiness gate: "
            "provenance plus independent evidence"
        )
    )
    ap.add_argument("--manifest", required=True, help="ScrolIQ provenance manifest JSON")
    ap.add_argument("--evidence", required=True, help="independent evidence ledger JSON")
    ap.add_argument(
        "--root-dir",
        required=True,
        help="submission package root; required so native evidence is re-verified",
    )
    ap.add_argument("--out", default=None, help="optional JSON readiness report")
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    evidence_path = Path(args.evidence)
    manifest_raw = manifest_path.read_bytes()
    evidence_raw = evidence_path.read_bytes()
    report = validate_readiness(
        json.loads(manifest_raw),
        json.loads(evidence_raw),
        root_dir=Path(args.root_dir) if args.root_dir else None,
        provenance_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        evidence_ledger_sha256=hashlib.sha256(evidence_raw).hexdigest(),
    )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "github":
        for item in report["blockers"]:
            print(
                f"::error title={item.get('code') or 'GP_READY_BLOCKED'}::"
                f"{item.get('path') or item.get('source')}: {item.get('message')}"
            )
        for item in report["unknowns"]:
            print(
                f"::warning title=GP_READY_UNKNOWN::"
                f"{item.get('claim')}: {item.get('message')}"
            )
        print(f"Grand Prize pre-submission readiness: {report['status'].upper()}")
    else:
        print(f"Grand Prize pre-submission readiness: {report['status'].upper()}")
        for item in report["blockers"]:
            print(
                f"- BLOCKER {item.get('code') or item.get('source')}: "
                f"{item.get('message')}"
            )
        for item in report["unknowns"]:
            suffix = ""
            if item.get("missing_mesh_ids"):
                suffix = f" missing={item['missing_mesh_ids']}"
            print(
                f"- UNKNOWN {item.get('claim')}: {item.get('message')}{suffix}"
            )

    raise SystemExit(0 if report["status"] == "ready" else 1)


if __name__ == "__main__":
    main()
