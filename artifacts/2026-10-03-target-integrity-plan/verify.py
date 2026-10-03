#!/usr/bin/env python3
"""Verify exact-volume ZPA reports before promoting target input_integrity."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from zpa.report import validate_report

HEX64 = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def verify_one(plan: dict[str, Any], reports_dir: Path) -> dict[str, Any]:
    path = reports_dir / plan["report"]
    require(path.is_file(), f"missing report: {path}")
    gate = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(gate, dict), f"{path}: gate output must be an object")
    require(gate.get("base") == "s3://vesuvius-challenge-open-data/", f"{path}: wrong base")
    require(gate.get("n_roots") == 1, f"{path}: n_roots must be 1")
    require(gate.get("n_fail") == 0, f"{path}: n_fail must be 0")
    expected = float(plan["expected_voxel_size_um"])
    observed_expected = gate.get("expected_voxel_size_um")
    require(
        isinstance(observed_expected, (int, float))
        and not isinstance(observed_expected, bool)
        and math.isclose(float(observed_expected), expected, rel_tol=0.0, abs_tol=1e-12),
        f"{path}: top-level expected voxel size mismatch",
    )

    results = gate.get("results")
    require(isinstance(results, list) and len(results) == 1, f"{path}: need exactly one result")
    result = results[0]
    require(isinstance(result, dict), f"{path}: result must be an object")
    require(result.get("root") == plan["root"], f"{path}: exact root mismatch")
    require(result.get("verdict") == "pass", f"{path}: verdict is not pass")
    require(result.get("fail") is False, f"{path}: fail flag is not false")
    require(result.get("integrity") == "PASS", f"{path}: integrity is not PASS")

    voxel = result.get("voxel_size_check")
    require(isinstance(voxel, dict), f"{path}: voxel_size_check missing")
    require(voxel.get("status") == "match", f"{path}: voxel-size fence did not match")
    require(
        isinstance(voxel.get("expected_um"), (int, float))
        and not isinstance(voxel.get("expected_um"), bool)
        and math.isclose(float(voxel["expected_um"]), expected, rel_tol=0.0, abs_tol=1e-12),
        f"{path}: voxel_size_check expected_um mismatch",
    )

    report = result.get("report")
    require(isinstance(report, dict), f"{path}: embedded report missing")
    schema_errors = validate_report(report)
    require(not schema_errors, f"{path}: ZPA report schema errors: {schema_errors[:3]}")
    require(report.get("root") == plan["root"], f"{path}: embedded report root mismatch")
    require(report.get("integrity") == "PASS", f"{path}: embedded report integrity is not PASS")

    att = report.get("source_attestation")
    require(isinstance(att, dict), f"{path}: source_attestation missing")
    require(att.get("algorithm") == "zpa-metadata-semantics-v1", f"{path}: attestation algorithm mismatch")
    require(att.get("state") == "PRESENT", f"{path}: source attestation is not PRESENT")
    require(att.get("axes") == ["z", "y", "x"], f"{path}: source axes are not exact ZYX")
    digest = att.get("metadata_semantics_sha256")
    require(isinstance(digest, str) and HEX64.fullmatch(digest) is not None, f"{path}: metadata semantics digest invalid")

    return {
        "scroll": plan["scroll"],
        "volume_id": plan["volume_id"],
        "root": plan["root"],
        "state": "pass",
        "gate_report": {
            "path": path.name,
            "sha256": sha256_file(path),
        },
        "voxel_size_check": voxel,
        "source_attestation": att,
        "claim": "Exact prize CT passed the pinned source-attested ZPA gate and eligible voxel-size fence.",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--reports-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        raise VerificationError(f"refusing to overwrite {out}")
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    require(plan.get("schema_version") == 1, "integrity plan schema_version must be 1")
    targets = plan.get("targets")
    require(isinstance(targets, list) and len(targets) == 3, "plan must contain exactly three targets")

    evidence = {
        "schema_version": 1,
        "as_of": plan.get("as_of"),
        "diagnostic": "grand-prize-target-input-integrity",
        "zpa": plan.get("zpa"),
        "plan": {
            "path": plan_path.as_posix(),
            "sha256": sha256_file(plan_path),
        },
        "targets": [verify_one(row, Path(args.reports_dir)) for row in targets],
        "claim_boundary": (
            "PASS closes only the target input-integrity/provenance prerequisite. "
            "It does not establish surface identity, held-out fit performance, ink, "
            "legibility, or Grand Prize readiness."
        ),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
